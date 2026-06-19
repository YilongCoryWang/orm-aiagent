import { Injectable, NotFoundException } from "@nestjs/common";
import { PrismaService } from "../prisma/prisma.service";
import { CreateProductDto } from "./dto/create-product.dto";
import { UpdateProductDto } from "./dto/update-product.dto";
import { Product } from "@prisma/client";

@Injectable()
export class ProductService {
  constructor(private prisma: PrismaService) {}

  async create(createProductDto: CreateProductDto): Promise<Product> {
    return this.prisma.product.create({
      data: createProductDto,
    });
  }

  async findAll(): Promise<Product[]> {
    return this.prisma.product.findMany();
  }

  async findOne(id: number): Promise<Product> {
    const product = await this.prisma.product.findUnique({
      where: { id },
    });
    if (!product) {
      throw new NotFoundException(`Product with ID ${id} not found`);
    }
    return product;
  }

  async update(
    id: number,
    updateProductDto: UpdateProductDto,
  ): Promise<Product> {
    await this.findOne(id);
    return this.prisma.product.update({
      where: { id },
      data: updateProductDto,
    });
  }

  async remove(id: number): Promise<Product> {
    await this.findOne(id);
    return this.prisma.product.delete({
      where: { id },
    });
  }

  // ── Business-logic methods (reference individual schema fields) ──
  // These exist so the Agent has real code to analyse when the schema changes.
  // If a field is renamed (e.g. quantity → stock), the Agent must find and
  // update every reference in these methods — that's the value of the LLM.

  /** Find products with stock > 0.  References field: stock */
  async findInStock(): Promise<Product[]> {
    return this.prisma.product.findMany({
      where: { stock: { gt: 0 } },
    });
  }

  /** Increment a product's stock.  References field: stock */
  async restockProduct(id: number, amount: number): Promise<Product> {
    await this.findOne(id);
    return this.prisma.product.update({
      where: { id },
      data: { stock: { increment: amount } },
    });
  }

  /** Find products by category.  References field: category */
  async findByCategory(category: string): Promise<Product[]> {
    return this.prisma.product.findMany({
      where: { category },
    });
  }

  /** Find products within a price range.  References field: price */
  async findByPriceRange(
    minPrice: number,
    maxPrice: number,
  ): Promise<Product[]> {
    return this.prisma.product.findMany({
      where: {
        price: { gte: minPrice, lte: maxPrice },
      },
    });
  }
}
